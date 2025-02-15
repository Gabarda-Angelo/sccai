<!-- dashboard.php (POS component) -->
<?php

include_once 'connectdb.php';
session_start();

// Redirect to login if user not logged in
if (empty($_SESSION['email'])) {
  header('location:../index.php');
  exit;
}

include_once "header.php";

// 1. Invoice summary (from invoices table)
$select = $pdo->prepare("SELECT SUM(total) AS gt, COUNT(invoice_id) AS invoice FROM invoices");
$select->execute();
$row = $select->fetch(PDO::FETCH_OBJ);
$total_order = $row->invoice;
$grand_total = $row->gt;

// 2. Total products (from products table)
$select = $pdo->prepare("SELECT COUNT(product_id) AS pname FROM products");
$select->execute();
$row = $select->fetch(PDO::FETCH_OBJ);
$total_product = $row->pname;

// 3. Total categories (from categories table)
$select = $pdo->prepare("SELECT COUNT(category_name) AS cate FROM categories");
$select->execute();
$row = $select->fetch(PDO::FETCH_OBJ);
$total_category = $row->cate;

?>
<!-- ChartJS -->
<script src="../plugins/chart.js/Chart.min.js"></script>
<!-- Content Wrapper. Contains page content -->
<div class="content-wrapper">
  <!-- Content Header (Page header) -->
  <div class="content-header">
    <div class="container-fluid">
      <div class="row mb-2">
        <div class="col-sm-6">
          <h1 class="m-0">Dashboard Overview</h1>
        </div><!-- /.col -->
        <div class="col-sm-6">
          <ol class="breadcrumb float-sm-right">
            <!-- Breadcrumbs if needed -->
          </ol>
        </div><!-- /.col -->
      </div><!-- /.row -->
    </div><!-- /.container-fluid -->
  </div>
  <!-- /.content-header -->

  <!-- Main content -->
  <div class="content">
    <div class="container-fluid">
      <div class="row">
        <div class="col-lg-12">

          <div class="row">
            <!-- Total Invoice -->
            <div class="col-lg-3 col-6">
              <div class="small-box bg-danger">
                <div class="inner">
                  <h3><?php echo $total_order; ?></h3>
                  <p>TOTAL INVOICE</p>
                </div>
                <div class="icon">
                  <i class="ion ion-bag"></i>
                </div>
                <a href="#" class="small-box-footer">
                  More info <i class="fas fa-arrow-circle-right"></i>
                </a>
              </div>
            </div>
            <!-- Total Revenue -->
            <div class="col-lg-3 col-6">
              <div class="small-box bg-success">
                <div class="inner">
                  <h3><?php echo number_format($grand_total, 2); ?></h3>
                  <p>TOTAL REVENUE(INR)</p>
                </div>
                <div class="icon">
                  <i class="ion ion-stats-bars"></i>
                </div>
                <a href="#" class="small-box-footer">
                  More info <i class="fas fa-arrow-circle-right"></i>
                </a>
              </div>
            </div>
            <!-- Total Products -->
            <div class="col-lg-3 col-6">
              <div class="small-box bg-warning">
                <div class="inner">
                  <h3><?php echo $total_product; ?></h3>
                  <p>TOTAL PRODUCT</p>
                </div>
                <div class="icon">
                  <i class="ion ion-person-add"></i>
                </div>
                <a href="#" class="small-box-footer">
                  More info <i class="fas fa-arrow-circle-right"></i>
                </a>
              </div>
            </div>
            <!-- Total Categories -->
            <div class="col-lg-3 col-6">
              <div class="small-box bg-info">
                <div class="inner">
                  <h3><?php echo $total_category; ?></h3>
                  <p>TOTAL CATEGORY</p>
                </div>
                <div class="icon">
                  <i class="ion ion-pie-graph"></i>
                </div>
                <a href="#" class="small-box-footer">
                  More info <i class="fas fa-arrow-circle-right"></i>
                </a>
              </div>
            </div>
          </div>
          <!-- /.row -->

          <!-- Earnings by Date Chart -->
          <div class="card card-danger card-outline">
            <div class="card-header">
              <h5 class="m-0">Earning By Date</h5>
            </div>
            <div class="card-body">
              <?php
              // Fetch total earnings grouped by order_date from the invoices table
              $select = $pdo->prepare("SELECT order_date, SUM(total) AS total FROM invoices GROUP BY order_date ORDER BY order_date ASC LIMIT 50");
              $select->execute();
              $ttl = [];
              $date = [];
              while ($row = $select->fetch(PDO::FETCH_ASSOC)) {
                $ttl[] = $row['total'];
                $date[] = $row['order_date'];
              }
              ?>
              <div>
                <canvas id="myChart" style="height: 250px"></canvas>
              </div>
            </div>
            <script>
              const ctx = document.getElementById('myChart');
              new Chart(ctx, {
                type: 'bar',
                data: {
                  labels: <?php echo json_encode($date); ?>,
                  datasets: [{
                    label: 'Total Earning',
                    backgroundColor: 'rgb(160,4,4)',
                    borderColor: 'rgb(160,4,4)',
                    data: <?php echo json_encode($ttl); ?>,
                    borderWidth: 1
                  }]
                },
                options: {
                  scales: {
                    y: {
                      beginAtZero: true
                    }
                  }
                }
              });
            </script>
          </div>

          <div class="row">
            <!-- Best Selling Product Table -->
            <div class="col-md-6">
              <div class="card card-danger card-outline">
                <div class="card-header">
                  <h5 class="m-0">BEST SELLING PRODUCT</h5>
                </div>
                <div class="card-body">
                  <table class="table table-striped table-hover" id="table_bestsellingproduct">
                    <thead>
                      <tr>
                        <td>Product ID</td>
                        <td>Product Name</td>
                        <td>QTY</td>
                        <td>Rate</td>
                        <td>Total</td>
                      </tr>
                    </thead>
                    <tbody>
                      <?php
                      // Query to get best selling products (joining invoice_details and products)
                      $select = $pdo->prepare("
                        SELECT id.product_id, p.product_name, SUM(id.quantity) AS q, MAX(id.unit_price) AS rate, SUM(id.total_price) AS total
                        FROM invoice_details id
                        JOIN products p ON id.product_id = p.product_id
                        GROUP BY id.product_id
                        ORDER BY SUM(id.quantity) DESC
                        LIMIT 10
                      ");
                      $select->execute();
                      while ($row = $select->fetch(PDO::FETCH_OBJ)) {
                        echo '
                          <tr>
                            <td>' . $row->product_id . '</td>
                            <td><span class="badge badge-dark">' . $row->product_name . '</span></td>
                            <td><span class="badge badge-success">' . $row->q . '</span></td>
                            <td><span class="badge badge-primary">' . $row->rate . '</span></td>
                            <td><span class="badge badge-danger">' . $row->total . '</span></td>
                          </tr>
                        ';
                      }
                      ?>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <!-- Recent Orders Table -->
            <div class="col-md-6">
              <div class="card card-danger card-outline">
                <div class="card-header">
                  <h5 class="m-0">Earning By Date</h5>
                </div>
                <div class="card-body">
                  <table class="table table-striped table-hover" id="table_recentorder">
                    <thead>
                      <tr>
                        <td>Invoice ID</td>
                        <td>Order Date</td>
                        <td>Total</td>
                        <td>Payment Type</td>
                      </tr>
                    </thead>
                    <tbody>
                      <?php
                      // Query for recent orders from the invoices table
                      $select = $pdo->prepare("SELECT * FROM invoices ORDER BY invoice_id DESC LIMIT 30");
                      $select->execute();
                      while ($row = $select->fetch(PDO::FETCH_OBJ)) {
                        echo '
                          <tr>
                            <td><a href="editorderpos.php?id=' . $row->invoice_id . '">' . $row->invoice_id . '</a></td>
                            <td><span class="badge badge-dark">' . $row->order_date . '</span></td>
                            <td><span class="badge badge-danger">' . $row->total . '</span></td>';
                        if ($row->payment_type == "Cash") {
                          echo '<td><span class="badge badge-warning">' . $row->payment_type . '</span></td>';
                        } else if ($row->payment_type == "Card") {
                          echo '<td><span class="badge badge-success">' . $row->payment_type . '</span></td>';
                        } else {
                          echo '<td><span class="badge badge-danger">' . $row->payment_type . '</span></td>';
                        }
                        echo '</tr>';
                      }
                      ?>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>

          

        </div>
      </div>
      <!-- /.row -->
    </div><!-- /.container-fluid -->
  </div>
  <!-- /.content -->
</div>
<!-- /.content-wrapper -->

<?php
include_once "footer.php";
?>

<script>
  $(document).ready(function() {
    $('#table_recentorder').DataTable({
      "order": [[0, "desc"]]
    });
  });
</script>
